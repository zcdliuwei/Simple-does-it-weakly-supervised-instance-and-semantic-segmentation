import os
import sys
import tensorflow as tf
import numpy as np
import math
import matplotlib as mlp
import copy
import random
import tqdm


BASEDIR = os.path.join(os.path.dirname(__file__), '..')

sys.path.insert(0, BASEDIR)

from Dataset.load import Load
from Parser_.parser import model_parser
from Dataset.save_result import Save
from Postprocess.dense_CRF import dense_CRF

mlp.use('Agg')

args = model_parser()

# parameter for Loading
DATASET = args.dataset
SET_NAME = args.set_name
LABEL_DIR_NAME = args.label_dir_name
IMG_DIR_NAME = args.img_dir_name

# dataset
# classes for segmentation
# default: 21
CLASS = args.classes
# training set size
# default: get from loading data
TRAIN_SIZE = None
# testing set size
# default: get from loading data
TEST_SIZE = None


# output format
SPACE = 15

# tqdm parameter
UNIT_SCALE = True
BAR_FORMAT = '{}{}{}'.format('{l_bar}', '{bar}', '| {n_fmt}/{total_fmt}')

# hyperparameter
# batch size
# default: 16
BATCH_SIZE = args.batch_size
# epoch
# default: 2000
EPOCH = args.epoch
# learning rate
# defalut: 0.01
LR = args.learning_rate
# momentum for optimizer
# default: 0.9
MOMENTUM = tf.Variable(args.momentum)
# probability for dropout
# default: 0.5
KEEP_PROB = args.keep_prob
# training or testing
# default: False
IS_TRAIN = args.is_train
# iteration
# ITER = TRAIN_SIZE/BATCH_SIZE
ITER = None
# widht and height after resize
# get from loading data
WIDTH = args.width
HEIGHT = args.height
# learning decay step
# default: 500
DECAY_STEP = 500
# learning rate decay rate
# default: 0.1
DECAY_RATE = 0.1
# staircase
# default: True
STAIRCASE = True
# weight decay
# default = 0.0005
WEIGHT_DECAY = 0.0005

# saving and restore weight
# VGG_16
VGG16_CKPT_PATH = BASEDIR + "/Model/models/vgg_16.ckpt"
# saving weight each SAVE_STEP
# default: 2
SAVE_STEP = args.save_step
# resore weights number
RESTORE_TARGET = int(args.restore_target)
# restore weights path
RESTORE_CKPT_PATH = BASEDIR + "/Model/models/model_" + \
                    str(RESTORE_TARGET) + ".ckpt"

# location for saving results
PRED_DIR_PATH = DATASET + '/' + args.pred_dir_name
PAIR_DIR_PATH = DATASET + '/' + args.pair_dir_name
CRF_DIR_PATH = DATASET + '/' + args.crf_dir_name
CRF_PAIR_DIR_PATH = DATASET + '/' + args.crf_pair_dir_name

# define placeholder
xp = tf.placeholder(tf.float32, shape=(None, None, None, 3))
yp = tf.placeholder(tf.int32, shape=(None, None, None, 1))
global_step = tf.placeholder(tf.int32)

# set gpu utilization
# config gpu utilization
config = tf.ConfigProto()
config.gpu_options.allow_growth = True


# build convolution layer for deeplab
def build_conv(input_, shape, name, weight_decay=WEIGHT_DECAY,
               strides=[1, 1, 1, 1], padding='SAME', activation=True,
               c_name='PRETRAIN_VGG16', holes=None):
    # tf.AUTO_REUSE for using exist variable
    with tf.variable_scope(name, reuse=tf.AUTO_REUSE):
        # define l2 regularizer
        regularizer = tf.contrib.layers.l2_regularizer(scale=weight_decay)
        # define initializer for weights and biases
        w_initializer = tf.contrib.layers.xavier_initializer()
        b_initializer = tf.zeros_initializer()
        # define variable for weights and biases
        biases = tf.get_variable(initializer=b_initializer, shape=shape[-1],
                                 name='biases',
                                 collections=[c_name, tf.GraphKeys.
                                              GLOBAL_VARIABLES])
        kernel = tf.get_variable(initializer=w_initializer, shape=shape,
                                 name='weights',
                                 collections=[c_name, tf.GraphKeys.
                                              GLOBAL_VARIABLES],
                                 regularizer=regularizer)
        # convolution
        if not holes:
            layer = tf.nn.conv2d(input=input_, filter=kernel, strides=strides,
                                 padding=padding)
        else:
            layer = tf.nn.atrous_conv2d(value=input_, filters=kernel,
                                        rate=holes, padding=padding)
        # add biases
        layer = tf.nn.bias_add(layer, biases)
        # use activation or not
        if activation:
            layer = tf.nn.relu(tf.layers.batch_normalization(inputs=layer,
                                                             axis=-1,
                                                             training=IS_TRAIN)
                               )
    return layer


# define network
def network():
    # get input from placeholder
    x = xp
    y = yp
    # get batch size, width, height
    BATCH_SIZE = tf.shape(x)[0]
    WIDTH = tf.shape(x)[2]
    HEIGHT = tf.shape(x)[1]
    # learning rate schedule
    lr = tf.train.exponential_decay(LR, global_step, DECAY_STEP, DECAY_RATE,
                                    STAIRCASE)
    # DeepLab-LargeFOV
    with tf.variable_scope('vgg_16'):
        with tf.variable_scope('conv1'):
            layer1 = build_conv(x, [3, 3, 3, 64], 'conv1_1')
            layer2 = build_conv(layer1, [3, 3, 64, 64], 'conv1_2')
            pool1 = tf.nn.max_pool(value=layer2, ksize=[1, 3, 3, 1],
                                   strides=[1, 2, 2, 1], padding='SAME',
                                   name='pool1')
        with tf.variable_scope('conv2'):
            layer3 = build_conv(pool1, [3, 3, 64, 128], 'conv2_1')
            layer4 = build_conv(layer3, [3, 3, 128, 128], 'conv2_2')
            pool2 = tf.nn.max_pool(value=layer4, ksize=[1, 3, 3, 1],
                                   strides=[1, 2, 2, 1], padding='SAME',
                                   name='pool2')
        with tf.variable_scope('conv3'):
            layer5 = build_conv(pool2, [3, 3, 128, 256], 'conv3_1')
            layer6 = build_conv(layer5, [3, 3, 256, 256], 'conv3_2')
            layer7 = build_conv(layer6, [3, 3, 256, 256], 'conv3_3')
            pool3 = tf.nn.max_pool(value=layer7, ksize=[1, 3, 3, 1],
                                   strides=[1, 2, 2, 1], padding='SAME',
                                   name='pool3')
        with tf.variable_scope('conv4'):
            layer8 = build_conv(pool3, [3, 3, 256, 512], 'conv4_1')
            layer9 = build_conv(layer8, [3, 3, 512, 512], 'conv4_2')
            layer10 = build_conv(layer9, [3, 3, 512, 512], 'conv4_3')
            pool4 = tf.nn.max_pool(value=layer10, ksize=[1, 3, 3, 1],
                                   strides=[1, 1, 1, 1], padding='SAME',
                                   name='pool4')
        with tf.variable_scope('conv5'):
            layer11 = build_conv(pool4, [3, 3, 512, 512], 'conv5_1', holes=2)
            layer12 = build_conv(layer11, [3, 3, 512, 512], 'conv5_2', holes=2)
            layer13 = build_conv(layer12, [3, 3, 512, 512], 'conv5_3', holes=2)
            pool5 = tf.nn.max_pool(value=layer13, ksize=[1, 3, 3, 1],
                                   strides=[1, 1, 1, 1], padding='SAME',
                                   name='pool5')
            pool5_1 = tf.nn.avg_pool(value=pool5, ksize=[1, 3, 3, 1],
                                     strides=[1, 1, 1, 1], padding='SAME',
                                     name='pool5_1')
        layer14 = build_conv(pool5_1, [3, 3, 512, 1024], 'fc6', padding='SAME',
                             c_name='UNPRETRAIN', holes=12)
        dropout6 = tf.nn.dropout(layer14, keep_prob=KEEP_PROB, name='dropout6')
        layer15 = build_conv(dropout6, [1, 1, 1024, 1024], 'fc7',
                             padding='VALID', c_name='UNPRETRAIN')
        dropout7 = tf.nn.dropout(layer15, keep_prob=KEEP_PROB, name='dropout7')

        layer16 = build_conv(dropout7, [1, 1, 1024, CLASS], 'fc8',
                             padding='VALID', activation=False,
                             c_name='UNPRETRAIN_LAST')

        predictions = layer16

    # to one-hot
    y = tf.reshape(y, shape=[BATCH_SIZE, -1])
    y = tf.one_hot(y, depth=CLASS)
    y = tf.reshape(y, shape=[-1, CLASS])
    # resize predictions for cross entropy
    predictions = tf.image.resize_bilinear(predictions, [HEIGHT, WIDTH])
    predictions = tf.reshape(predictions, [-1, CLASS])
    prob_prediction = tf.reshape(tf.nn.softmax(predictions),
                                 [BATCH_SIZE, HEIGHT, WIDTH, CLASS])

    # define loss function
    with tf.variable_scope('loss'):
        loss = -tf.reduce_mean(y*tf.log(tf.nn.softmax(predictions)+1e-10))
        tf.summary.scalar('loss', loss)

    # get variables
    last_var = tf.get_collection('UNPRETRAIN_LAST')
    other_var = list(set(tf.global_variables()) - set(last_var))
    # operations for batch normalization
    update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
    # define optimizer
    with tf.variable_scope('optimizer'):
        # batch normalization operations added as a dependency
        with tf.control_dependencies(update_ops):
            optimizer1 = tf.train.MomentumOptimizer(
                    learning_rate=lr, momentum=MOMENTUM).minimize(
                            loss, var_list=other_var)
            optimizer2 = tf.train.MomentumOptimizer(
                    learning_rate=lr*10, momentum=MOMENTUM).minimize(
                            loss, var_list=last_var)
            optimizer = tf.group(optimizer1, optimizer2)

    # resize to image format
    predictions = tf.argmax(predictions, axis=1)
    predictions = tf.reshape(predictions, [BATCH_SIZE, HEIGHT, WIDTH, 1])

    return loss, optimizer, predictions, prob_prediction


# shuffle data
def shuffle_unison(x, y):
    state = np.random.get_state()
    np.random.shuffle(x)
    np.random.set_state(state)
    np.random.shuffle(y)


# augmentation
def augmentation(img, label):
    img_ = []
    label_ = []
    h = int(HEIGHT*0.626)
    w = int(WIDTH*0.626)
    for i in range(img.shape[0]):
        # random crop
        shift1 = random.randint(0, HEIGHT - h)
        shift2 = random.randint(0, WIDTH - w)
        img_.append(img[i][shift1:h + shift1, shift2:w + shift2][:])
        label_.append(label[i][shift1:h + shift1, shift2:w + shift2][:])
        # flip
        if random.randint(0, 1) == 0:
            img_[i] = np.flip(img_[i], 1)
            label_[i] = np.flip(label_[i], 1)
    return img_, label_


# mean substraction by RGB
def mean_substraction(x):
    # Uncomment these block if you train on other dataset.
    # Change the dtyp of x in load.py to np.float64 to get the precision.
    # Then replace mean and std with new mean and new std.
    """
    mean = np.mean(x, axis = (0, 1, 2))
    print ('{:{}}: {}'.format('Mean', SPACE, mean))
    std = np.std(x, axis = (0, 1, 2))
    print ('{:{}}: {}'.format('Std', SPACE, std))
    """
    # Mean and Std computed from VOC train set
    mean = [116.47913155, 112.99590528, 104.12249927]
    std = [69.29213195, 68.4138099, 72.42007962]
    if IS_TRAIN:
        for i in range(3):
            x[:, :, :, i] = (x[:, :, :, i] - mean[i]) / (std[i] + 1e-7)
    else:
        for i in range(TEST_SIZE):
            for j in range(3):
                x[i][:, :, j] = (x[i][:, :, j] - mean[j]) / (std[j] + 1e-7)
    return x


# training
def train_network(x_train, y_train):
    with tf.Session() as sess:
        # get network
        loss, optimizer, predictions, prob_predictions = network()
        # setup tensorboard
        merged = tf.summary.merge_all()
        writer = tf.summary.FileWriter(BASEDIR + "/Model/Logs/", sess.graph)
        if RESTORE_TARGET == 0:
            pretrain_var = tf.get_collection('PRETRAIN_VGG16')
            other_var = list(set(tf.global_variables()) - set(pretrain_var))
            # setup saver and restorer
            saver = tf.train.Saver(tf.global_variables(), max_to_keep=1000)
            restorer = tf.train.Saver(pretrain_var)
            # load weight for untrainable variables
            restorer.restore(sess, VGG16_CKPT_PATH)
            # initial unpretrain variables
            init = tf.variables_initializer(other_var)
            sess.run(init)
        else:
            # setup saver
            saver = tf.train.Saver(tf.global_variables(), max_to_keep=1000)
            # load weight
            saver.restore(sess, RESTORE_CKPT_PATH)
        # training
        for i in range(RESTORE_TARGET, EPOCH):
            print('{:{}}: {}'.format('Epoch', SPACE, i))
            # shuffle data
            shuffle_unison(x_train, y_train)
            # split for batch
            x_train_ = np.array_split(x_train, ITER)
            y_train_ = np.array_split(y_train, ITER)
            # save weight
            if i % SAVE_STEP == 0:
                saver.save(sess, BASEDIR + "/Model/models/model_" +
                           str(i) + ".ckpt")
            avg_loss = 0
            count = 0
            for j in tqdm.tqdm(range(ITER), desc='{:{}}'.
                               format('Epoch' + str(i), SPACE),
                               unit_scale=UNIT_SCALE, bar_format=BAR_FORMAT):
                # check empty or not
                if x_train_[j].size:
                    # augmentation
                    x_train_[j], y_train_[j] = augmentation(x_train_[j],
                                                            y_train_[j])
                    summary, optimizer_, loss_ = sess.run(
                            [merged, optimizer, loss],
                            feed_dict={xp: x_train_[j],
                                       yp: y_train_[j],
                                       global_step: i})
                    avg_loss = avg_loss + loss_
                    count = count + 1
                    writer.add_summary(summary, i * ITER + j)
            print('{:{}}: {}'.format('Average Loss', SPACE, avg_loss / count))
        writer.close()


# testing
def test_network(x_test, img_names):
    with tf.Session(config=config) as sess:
        # get network
        loss, optimizer, predictions, prob_predictions = network()
        # setup restorer
        restorer = tf.train.Saver(tf.global_variables())
        # mean substraction
        x_test_ = mean_substraction(copy.deepcopy(x_test))
        # load weight
        restorer.restore(sess, RESTORE_CKPT_PATH)
        for i in tqdm.tqdm(range(TEST_SIZE), desc='{:{}}'.
                           format('Test and save', SPACE),
                           unit_scale=UNIT_SCALE, bar_format=BAR_FORMAT):
            predictions_, prob_predictions_ = sess.run(
                    [predictions, prob_predictions],
                    feed_dict={xp: [x_test_[i]]})
            save_ = Save(x_test[i].astype(np.uint8), np.squeeze(predictions_),
                         img_names[i], PRED_DIR_PATH, PAIR_DIR_PATH, CLASS)
            save_.save()

            dense_CRF_ = dense_CRF(x_test[i].astype(np.uint8),
                                   prob_predictions_[0])
            crf_mask = dense_CRF_.run_dense_CRF()
            save_ = Save(x_test[i].astype(np.uint8), crf_mask, img_names[i],
                         CRF_DIR_PATH, CRF_PAIR_DIR_PATH, CLASS)
            save_.save()


def main():
    global WIDTH
    global HEIGHT
    global TRAIN_SIZE
    global KEEP_PROB
    global TEST_SIZE
    global ITER
    global BATCH_SIZE

    if IS_TRAIN:
        # load training data from VOC12 dataset
        dataset = Load(IS_TRAIN, DATASET, SET_NAME, LABEL_DIR_NAME,
                       IMG_DIR_NAME, WIDTH, HEIGHT)
        x_train, y_train = dataset.load_data()
        # mean substraction
        x_train = mean_substraction(x_train)
        # set training set size
        TRAIN_SIZE = len(x_train)
        # get iteration
        ITER = math.ceil(TRAIN_SIZE / BATCH_SIZE)
        # get widht and height
        WIDTH = x_train[0].shape[1]
        HEIGHT = x_train[0].shape[0]
        # train network
        train_network(x_train, y_train)

    else:
        # load val data from VOC12 dataset
        dataset = Load(IS_TRAIN, DATASET, SET_NAME, LABEL_DIR_NAME,
                       IMG_DIR_NAME, WIDTH, HEIGHT)
        x_test, img_names = dataset.load_data()
        # set testing set size
        TEST_SIZE = len(x_test)
        # close dropout
        KEEP_PROB = 1
        # set batch size
        BATCH_SIZE = 1
        # test network
        test_network(x_test, img_names)


if __name__ == '__main__':
    main()
